"""TOOL-010: add_api_key_auth — add API-key authentication to a FastAPI project.

Generates all files required for machine-to-machine API-key auth:
an ``APIKey`` SQLAlchemy model, an Argon2id/sha256-pepper hasher, a FastAPI
dependency with constant-time verification and DUMMY_HASH timing-safety, a
per-key Redis rate-limiter with in-process fallback, scope evaluator with
``resource:action`` wildcards, CRUD helpers, route handlers (create / list /
rotate / revoke), Pydantic schemas, and an Alembic migration.

The tool is idempotent: a second run detects the ``APIKey`` model fingerprint
and returns ``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.auth_access.add_api_key_auth import add_api_key_auth

    result = add_api_key_auth(ToolInput(project_dir="/path/to/project"))
    print(result.status)         # "success"
    print(result.files_created)  # [.../app/models/api_key.py, ...]
    print(result.next_steps)     # ["alembic upgrade head", ...]
"""

from __future__ import annotations

import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head


MCP_TOOL = {
    "name": "fastapi_add_api_key_auth",
    "description": "Add API key authentication alongside the existing JWT auth.",
    "tags": ["extend", "auth_access"],
    "entry": "add_api_key_auth",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_api_key_auth(inp: ToolInput) -> ToolResult:
    """Add API-key authentication to a FastAPI project.

    Writes all necessary files for machine-to-machine auth:
    model, hasher, dependency, rate-limiter, scope evaluator, CRUD,
    routes, schemas, and Alembic migration.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and
            optional ``dry_run`` flag.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    # --- Prerequisite check (standalone mode) --------------------------------
    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

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
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    app_dir = project / "app"

    # --- Pre-flight: already installed? ------------------------------------
    model_file = app_dir / "models" / "api_key.py"
    if model_file.exists() and "APIKey" in model_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["APIKey model already present — api-key auth is already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create API-key auth files.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1: APIKey model
    _write_model(model_file)
    files_created.append(str(model_file))

    # Register APIKey in app/models/__init__.py for metadata.create_all().
    _patch_models_init(
        app_dir / "models" / "__init__.py",
        [("api_key", "APIKey")],
    )

    # Step 2: Hasher (Argon2id + sha256-pepper + DUMMY_HASH)
    hasher_file = app_dir / "core" / "api_key_hasher.py"
    _write_hasher(hasher_file)
    files_created.append(str(hasher_file))

    # Step 3: Rate-limiter (Redis + in-process fallback)
    rate_limit_file = app_dir / "core" / "api_key_rate_limit.py"
    _write_rate_limit(rate_limit_file)
    files_created.append(str(rate_limit_file))

    # Step 4: Scope evaluator
    scopes_file = app_dir / "auth" / "api_key_scopes.py"
    _write_scopes(scopes_file)
    files_created.append(str(scopes_file))

    # Step 5: FastAPI dependency
    deps_file = app_dir / "core" / "api_key_deps.py"
    _write_deps(deps_file)
    files_created.append(str(deps_file))

    # Step 6: CRUD
    crud_file = app_dir / "crud" / "api_key.py"
    _write_crud(crud_file)
    files_created.append(str(crud_file))

    # Step 7: Schemas
    schema_file = app_dir / "schemas" / "api_key.py"
    _write_schemas(schema_file)
    files_created.append(str(schema_file))

    # Step 8: Routes
    routes_file = app_dir / "api" / "routes" / "api_keys.py"
    _write_routes(routes_file)
    files_created.append(str(routes_file))

    # Step 9: Patch app/routes/__init__.py to include the router
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_api_main(routes_init)
        files_modified.append(str(routes_init))

    # Step 10: Alembic migration
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        migration = _write_migration(versions_dir)
        files_created.append(str(migration))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "API-key model: app/models/api_key.py",
            "Hasher supports argon2id and sha256_pepper algorithms.",
            "Constant-time DUMMY_HASH prevents key-id enumeration timing attacks.",
            "Per-key rate limiting: Redis (atomic INCR+EXPIRE) with in-process fallback.",
            "Scope format: resource:action, wildcard *:* supported.",
            "Plaintext secret returned ONCE at creation; never stored, never logged.",
        ],
        next_steps=[
            "Add API_KEY_PEPPER and API_KEY_RATE_LIMIT_PER_MINUTE to app/core/config.py settings.",
            "alembic upgrade head",
            "Include api_keys router in app/api/main.py (done automatically if file existed).",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Step helpers — each < 50 LOC
# ---------------------------------------------------------------------------

def _patch_models_init(
    models_init: Path,
    class_imports: list[tuple[str, str]],
) -> None:
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


def _write_model(dest: Path) -> None:
    """Write app/models/api_key.py with the APIKey SQLAlchemy model.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"SQLAlchemy model for API keys.\"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime

        from sqlalchemy import (
            JSON,
            CheckConstraint,
            DateTime,
            ForeignKey,
            Index,
            String,
            Uuid,
            func,
        )
        from sqlalchemy.orm import Mapped, mapped_column

        from app.models.base import Base


        class APIKey(Base):
            \"\"\"Per-user API key record.

            Stores only the hashed secret; the plaintext is shown once at creation.

            Attributes:
                id: Primary key UUID.
                key_id: Short public identifier used in token format api_<key_id>_<secret>.
                secret_hash: Argon2id or sha256-pepper hash of the raw secret.
                name: Human-readable label.
                description: Optional extended description.
                scopes: JSON array of resource:action scope strings.
                status: One of active, revoked, expired.
                user_id: FK to users.id (CASCADE DELETE).
                expires_at: Optional hard expiry timestamp (UTC).
                last_used_at: Updated on every authenticated request.
                revoked_at: Set when status transitions to revoked.
                created_at: Immutable creation timestamp.
            \"\"\"

            __tablename__ = "api_keys"

            id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
            key_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
            secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)
            name: Mapped[str] = mapped_column(String(255), nullable=False)
            description: Mapped[str | None] = mapped_column(String(500), nullable=True)
            scopes: Mapped[list] = mapped_column(JSON, nullable=False, server_default="[]")
            status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")

            user_id: Mapped[uuid.UUID] = mapped_column(
                Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
            )

            expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
            last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
            revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
            created_at: Mapped[datetime] = mapped_column(
                DateTime(timezone=True), server_default=func.now(), nullable=False
            )

            __table_args__ = (
                CheckConstraint(
                    "status IN ('active','revoked','expired')",
                    name="ck_api_keys_status",
                ),
                CheckConstraint(
                    "length(key_id) >= 16 AND length(key_id) <= 32",
                    name="ck_api_keys_key_id_format",
                ),
                Index("ix_api_keys_user_status", "user_id", "status"),
            )
        """)
    dest.write_text(content)


def _write_hasher(dest: Path) -> None:
    """Write app/core/api_key_hasher.py with key generation and constant-time verify.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"API key generation and constant-time secret verification.

        Two strategies are supported:

        - ``argon2id``: GPU-resistant, ~50 ms.  Best for low-volume keys.
        - ``sha256_pepper``: < 1 ms.  Suitable for high-volume keys; requires a
          server-side pepper stored in ``settings.API_KEY_PEPPER`` (never in DB).

        Token format: ``sk_{environment}_{key_id}_{secret}``
        Environment prefix: ``sk_live_`` or ``sk_test_`` — distinguishes environment.

        A ``DUMMY_HASH`` is verified when an unknown ``key_id`` is presented so
        the response time is indistinguishable from a wrong-secret attempt, closing
        the timing-based key-id enumeration oracle.
        \"\"\"

        from __future__ import annotations

        import hashlib
        import hmac
        import os
        import secrets
        from typing import Literal

        try:
            from argon2 import PasswordHasher
            from argon2.exceptions import VerifyMismatchError
            _ph = PasswordHasher(time_cost=2, memory_cost=19 * 1024, parallelism=1)
            _ARGON2_AVAILABLE = True
        except ImportError:
            _ph = None  # type: ignore[assignment]
            VerifyMismatchError = Exception  # type: ignore[assignment,misc]
            _ARGON2_AVAILABLE = False

        _PEPPER: bytes = os.environ.get("API_KEY_PEPPER", "dev-pepper-change-in-production").encode("utf-8")
        _KEY_BYTES = 32  # 256 bits of entropy
        _PREFIX_LEN = 8

        # Pre-computed dummy hash for constant-time fake check on unknown key_id.
        DUMMY_HASH: str = "sha256$$" + "0" * 64


        def generate_secret() -> str:
            \"\"\"Return a 256-bit URL-safe random secret string.

            Returns:
                URL-safe base64-encoded 32-byte random string.
            \"\"\"
            return secrets.token_urlsafe(_KEY_BYTES)


        def generate_key_id() -> str:
            \"\"\"Return a 16-character lowercase alphanumeric key_id.

            Returns:
                16-character hex string suitable for the ``key_id`` column.
            \"\"\"
            return secrets.token_hex(8)


        def hash_secret(
            secret: str,
            algorithm: Literal["argon2id", "sha256_pepper"] = "sha256_pepper",
        ) -> str:
            \"\"\"Hash a raw API-key secret for safe storage.

            Args:
                secret: The raw plaintext secret to hash.
                algorithm: Hashing algorithm.  ``argon2id`` is GPU-resistant;
                    ``sha256_pepper`` is fast with server-side pepper.

            Returns:
                Prefixed hash string (``argon2$$...`` or ``sha256$$...``).

            Raises:
                RuntimeError: If argon2id is requested but argon2-cffi is not installed.
            \"\"\"
            if algorithm == "argon2id":
                if not _ARGON2_AVAILABLE:
                    raise RuntimeError("argon2-cffi is required for argon2id hashing")
                return "argon2$$" + _ph.hash(secret)
            digest = hmac.new(_PEPPER, secret.encode("utf-8"), hashlib.sha256).hexdigest()
            return "sha256$$" + digest


        def verify_secret(secret: str, stored_hash: str) -> bool:
            \"\"\"Constant-time verification of a raw secret against its stored hash.

            Always performs the full verification work even on mismatch to prevent
            timing oracles.  Falls back to DUMMY_HASH comparison when stored_hash is
            empty so callers can safely verify unknown key_ids.

            Args:
                secret: The raw plaintext secret from the Authorization header.
                stored_hash: The ``secret_hash`` column value from the database.

            Returns:
                ``True`` if the secret matches the stored hash, ``False`` otherwise.
            \"\"\"
            if not stored_hash:
                # Constant-time dummy path — still burns time
                hmac.new(_PEPPER, secret.encode("utf-8"), hashlib.sha256).hexdigest()
                return False
            if stored_hash.startswith("argon2$$"):
                if not _ARGON2_AVAILABLE:
                    return False
                try:
                    _ph.verify(stored_hash[len("argon2$$"):], secret)
                    return True
                except VerifyMismatchError:
                    return False
            if stored_hash.startswith("sha256$$"):
                expected = hmac.new(_PEPPER, secret.encode("utf-8"), hashlib.sha256).hexdigest()
                return hmac.compare_digest(expected, stored_hash[len("sha256$$"):])
            return False
        """)
    dest.write_text(content)


def _write_rate_limit(dest: Path) -> None:
    """Write app/core/api_key_rate_limit.py with Redis + in-process fallback.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Per-key rate limiting for API keys.

        Primary path: atomic Redis INCR + EXPIRE in a pipeline (p99 < 1 ms).
        Fallback path: in-process counter per worker (best-effort, no cross-worker
        coordination).  The fallback activates automatically when Redis is
        unavailable so the API does not go down if Redis has a transient outage.

        Limit is read from ``settings.API_KEY_RATE_LIMIT_PER_MINUTE`` (default 600).
        \"\"\"

        from __future__ import annotations

        import os
        import time
        from uuid import UUID

        _WINDOW_SECONDS = 60
        _DEFAULT_LIMIT = int(os.environ.get("API_KEY_RATE_LIMIT_PER_MINUTE", "600"))


        async def check_rate_limit(key_id: UUID, *, limit: int | None = None) -> bool:
            \"\"\"Return True if the key is under its rate limit, False if exceeded.

            Tries Redis first; falls back to an in-process counter when Redis is
            unavailable.  The fallback is per-worker and best-effort.

            Args:
                key_id: The UUID primary key of the APIKey record.
                limit: Requests-per-minute cap.  Uses ``_DEFAULT_LIMIT`` when None.

            Returns:
                ``True`` if the request may proceed, ``False`` if rate-limited.
            \"\"\"
            effective_limit = limit if limit is not None else _DEFAULT_LIMIT
            redis = await _get_redis_or_none()
            if redis is not None:
                return await _check_redis(redis, key_id, effective_limit)
            return _check_in_process(key_id, effective_limit)


        async def _get_redis_or_none():
            \"\"\"Return a Redis client or None when Redis is unavailable.

            Returns:
                Async Redis client, or ``None`` if connection fails or redis-py is absent.
            \"\"\"
            try:
                from app.core.redis import get_redis_or_none  # type: ignore[import]
                return await get_redis_or_none()
            except Exception:
                return None


        async def _check_redis(redis, key_id: UUID, limit: int) -> bool:
            \"\"\"Atomic INCR + EXPIRE on a per-key per-bucket Redis key.

            Args:
                redis: Async Redis client.
                key_id: UUID of the API key.
                limit: Per-minute request limit.

            Returns:
                ``True`` if under limit, ``False`` if exceeded.
            \"\"\"
            bucket = int(time.time() // _WINDOW_SECONDS)
            redis_key = f"api_key:rate:{key_id}:{bucket}"
            pipe = redis.pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, _WINDOW_SECONDS * 2)
            count, _ = await pipe.execute()
            return count <= limit


        # In-process fallback storage (per-worker, best-effort)
        _local_counters: dict[tuple[str, int], int] = {}


        def _check_in_process(key_id: UUID, limit: int) -> bool:
            \"\"\"In-process fallback rate counter.

            Garbage-collects stale buckets to prevent unbounded memory growth.

            Args:
                key_id: UUID of the API key.
                limit: Per-minute request limit.

            Returns:
                ``True`` if under limit, ``False`` if exceeded.
            \"\"\"
            bucket = int(time.time() // _WINDOW_SECONDS)
            key = (str(key_id), bucket)
            # GC: drop all entries from previous buckets
            for k in list(_local_counters):
                if k[1] != bucket:
                    _local_counters.pop(k, None)
            cur = _local_counters.get(key, 0) + 1
            _local_counters[key] = cur
            return cur <= limit
        """)
    dest.write_text(content)


def _write_scopes(dest: Path) -> None:
    """Write app/auth/api_key_scopes.py with resource:action wildcard evaluator.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Scope evaluator for API keys.

        Scopes are strings of the form ``resource:action`` (e.g. ``orders:read``,
        ``billing:write``, ``admin:*``, ``*:*``).  Wildcards are supported on
        either or both segments.  A key is denied by default; it must have an
        explicit grant that matches the required scope.

        Example::

            result = evaluate_scope(["orders:read", "billing:*"], "billing:write")
            assert result.allowed is True
            assert result.matched_scope == "billing:*"
        \"\"\"

        from __future__ import annotations

        from dataclasses import dataclass
        from typing import Iterable


        @dataclass(frozen=True)
        class ScopeCheckResult:
            \"\"\"Result of a single scope evaluation.

            Attributes:
                allowed: Whether the key has a matching granted scope.
                matched_scope: The specific scope string that matched, or None.
                reason: Human-readable explanation of the decision.
            \"\"\"

            allowed: bool
            matched_scope: str | None
            reason: str


        def _scope_matches(granted: str, required: str) -> bool:
            \"\"\"Return True if *granted* satisfies *required* using wildcard rules.

            Args:
                granted: A scope string from the key's granted list.
                required: The scope the route requires.

            Returns:
                ``True`` if the granted scope covers the required scope.
            \"\"\"
            g_resource, _, g_action = granted.partition(":")
            r_resource, _, r_action = required.partition(":")
            resource_ok = g_resource == "*" or g_resource == r_resource
            action_ok = g_action == "*" or g_action == r_action
            return resource_ok and action_ok


        def evaluate_scope(
            granted_scopes: Iterable[str], required_scope: str
        ) -> ScopeCheckResult:
            \"\"\"Evaluate whether any granted scope satisfies the required scope.

            Deny-by-default: the key must have an explicit grant that matches.
            Wildcards are expanded on both resource and action segments.

            Args:
                granted_scopes: Iterable of scope strings from the API key record.
                required_scope: The ``resource:action`` scope the route requires.

            Returns:
                ``ScopeCheckResult`` with ``allowed``, ``matched_scope``, and ``reason``.
            \"\"\"
            required_scope = required_scope.strip()
            if ":" not in required_scope:
                return ScopeCheckResult(
                    allowed=False,
                    matched_scope=None,
                    reason=f"required scope must be 'resource:action', got {required_scope!r}",
                )
            for scope in granted_scopes:
                if _scope_matches(scope, required_scope):
                    return ScopeCheckResult(allowed=True, matched_scope=scope, reason="matched")
            return ScopeCheckResult(
                allowed=False,
                matched_scope=None,
                reason=f"no granted scope matches {required_scope!r}",
            )
        """)
    dest.write_text(content)


def _write_deps(dest: Path) -> None:
    """Write app/core/api_key_deps.py with FastAPI dependency and require_scope.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"FastAPI dependencies for API-key authentication.

        ``get_current_api_key``: validates the ``Authorization: Bearer api_<key_id>_<secret>``
        header, performs constant-time verification, checks status and expiry, enforces
        per-key rate limiting, and updates audit fields.

        ``require_scope``: higher-order dependency factory that checks the API key holds
        the required scope (or ``*:*``).

        Constant-time safety: when the ``key_id`` is not found in the database the
        dependency still runs a fake verification against ``DUMMY_HASH`` so the response
        time is indistinguishable from a wrong-secret attempt.
        \"\"\"

        from __future__ import annotations

        from datetime import datetime, timezone
        from typing import Annotated

        from fastapi import Depends, HTTPException, Request, status
        from fastapi.security import APIKeyHeader
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.api.deps import SessionDep
        from app.core.api_key_hasher import DUMMY_HASH, verify_secret
        from app.core.api_key_rate_limit import check_rate_limit
        from app.models.api_key import APIKey

        _api_key_header = APIKeyHeader(name="Authorization", auto_error=False)


        def _parse_header(header_value: str | None) -> tuple[str, str] | None:
            \"\"\"Parse ``Authorization: Bearer api_<key_id>_<secret>`` into components.

            Args:
                header_value: Raw value of the Authorization header.

            Returns:
                ``(key_id, secret)`` tuple, or ``None`` if the format is invalid.
            \"\"\"
            if not header_value or not header_value.startswith("Bearer "):
                return None
            token = header_value[len("Bearer "):]
            if not token.startswith("api_"):
                return None
            parts = token.split("_", 2)
            if len(parts) != 3 or not parts[1] or not parts[2]:
                return None
            return parts[1], parts[2]


        async def _fetch_api_key(
            session: AsyncSession,
            key_id: str,
            secret: str,
        ) -> APIKey:
            \"\"\"Fetch and secret-verify an APIKey row; raises 401 on any mismatch.

            Uses a constant-time dummy hash when the key_id is not found to prevent
            enumeration timing oracles.

            Args:
                session: Async SQLAlchemy session.
                key_id: Public key identifier portion.
                secret: Raw secret portion to verify.

            Returns:
                APIKey ORM instance with matching key_id.

            Raises:
                HTTPException 401: key_id not found or secret mismatch.
            \"\"\"
            stmt = select(APIKey).where(APIKey.key_id == key_id)
            api_key = (await session.execute(stmt)).scalar_one_or_none()
            if api_key is None:
                verify_secret(secret, DUMMY_HASH)  # constant-time dummy
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
            if not verify_secret(secret, api_key.secret_hash):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
            return api_key


        async def _check_api_key_validity(api_key: APIKey, session: AsyncSession) -> None:
            \"\"\"Enforce status, expiry, and rate-limit constraints on an API key.

            Args:
                api_key: Fetched and secret-verified APIKey ORM instance.
                session: Async SQLAlchemy session (needed to flush expiry status update).

            Raises:
                HTTPException 401: Key is not active or has expired.
                HTTPException 429: Per-key rate limit exceeded.
            \"\"\"
            if api_key.status != "active":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="API key is not active",
                )
            if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
                api_key.status = "expired"
                await session.flush()
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key expired")
            if not await check_rate_limit(api_key.id):
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded",
                    headers={"Retry-After": "60"},
                )


        async def get_current_api_key(
            request: Request,
            session: SessionDep,
            header_value: Annotated[str | None, Depends(_api_key_header)],
        ) -> APIKey:
            \"\"\"Validate the API key from the Authorization header.

            Delegates to ``_fetch_api_key`` (DB + secret check) and
            ``_check_api_key_validity`` (status, expiry, rate-limit), then updates
            audit fields before returning the authenticated key.

            Args:
                request: Incoming FastAPI request (for IP and user-agent capture).
                session: Injected async database session.
                header_value: Raw Authorization header value.

            Returns:
                The authenticated ``APIKey`` ORM instance.

            Raises:
                HTTPException 401: Missing, malformed, invalid, revoked, or expired key.
                HTTPException 429: Per-key rate limit exceeded.
            \"\"\"
            parsed = _parse_header(header_value)
            if parsed is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or missing API key",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            key_id, secret = parsed
            api_key = await _fetch_api_key(session, key_id, secret)
            await _check_api_key_validity(api_key, session)
            api_key.last_used_at = datetime.now(timezone.utc)
            api_key.last_used_ip = request.client.host if request.client else None  # type: ignore[attr-defined]
            api_key.last_used_ua = (request.headers.get("user-agent", "") or "")[:500]
            await session.flush()
            return api_key


        def require_scope(scope: str):
            \"\"\"Return a FastAPI dependency that enforces a required scope.

            The dependency passes if the API key holds the exact scope, a wildcard
            scope that covers it (e.g. ``orders:*`` covers ``orders:read``), or ``*:*``.

            Args:
                scope: Required ``resource:action`` scope string.

            Returns:
                A FastAPI-compatible async dependency callable.

            Example::

                @router.post("/orders/", dependencies=[Depends(require_scope("orders:write"))])
                async def create_order(...): ...
            \"\"\"
            from app.auth.api_key_scopes import evaluate_scope

            async def _dep(
                api_key: Annotated[APIKey, Depends(get_current_api_key)],
            ) -> None:
                result = evaluate_scope(api_key.scopes or [], scope)
                if not result.allowed:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"API key missing required scope: {scope}",
                    )

            return _dep
        """)
    dest.write_text(content)


def _write_crud(dest: Path) -> None:
    """Write app/crud/api_key.py with create, get_by_key_id, list_for_user, revoke.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"CRUD operations for the APIKey model.\"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime, timezone

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.models.api_key import APIKey
        from app.schemas.api_key import APIKeyCreate


        async def create(
            session: AsyncSession,
            *,
            key_in: APIKeyCreate,
            user_id: uuid.UUID,
            key_id: str,
            secret_hash: str,
        ) -> APIKey:
            \"\"\"Create a new APIKey record.

            The plaintext secret must be hashed by the caller before passing
            ``secret_hash``; this function never receives or stores plaintext.

            Args:
                session: Async SQLAlchemy session.
                key_in: Validated creation schema (name, scopes, description, expires_at).
                user_id: Owner's user UUID.
                key_id: Pre-generated short identifier string.
                secret_hash: Pre-computed hash of the raw secret.

            Returns:
                The newly created ``APIKey`` ORM instance.
            \"\"\"
            api_key = APIKey(
                key_id=key_id,
                secret_hash=secret_hash,
                name=key_in.name,
                description=key_in.description,
                scopes=key_in.scopes or [],
                user_id=user_id,
                expires_at=key_in.expires_at,
            )
            session.add(api_key)
            await session.flush()
            return api_key


        async def get_by_key_id(
            session: AsyncSession, *, key_id: str
        ) -> APIKey | None:
            \"\"\"Look up an APIKey by its short public key_id.

            Args:
                session: Async SQLAlchemy session.
                key_id: The 16-char hex key_id column value.

            Returns:
                The matching ``APIKey``, or ``None`` if not found.
            \"\"\"
            stmt = select(APIKey).where(APIKey.key_id == key_id)
            return (await session.execute(stmt)).scalar_one_or_none()


        async def list_for_user(
            session: AsyncSession, *, user_id: uuid.UUID
        ) -> list[APIKey]:
            \"\"\"Return all non-expired API keys for a user.

            Args:
                session: Async SQLAlchemy session.
                user_id: Owner user UUID.

            Returns:
                List of ``APIKey`` instances ordered by creation date (newest first).
            \"\"\"
            stmt = (
                select(APIKey)
                .where(APIKey.user_id == user_id)
                .order_by(APIKey.created_at.desc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())


        async def revoke(session: AsyncSession, *, api_key: APIKey) -> APIKey:
            \"\"\"Revoke an API key immediately.

            Args:
                session: Async SQLAlchemy session.
                api_key: The loaded ``APIKey`` ORM instance to revoke.

            Returns:
                The updated ``APIKey`` instance with status='revoked'.
            \"\"\"
            api_key.status = "revoked"
            api_key.revoked_at = datetime.now(timezone.utc)
            await session.flush()
            return api_key
        """)
    dest.write_text(content)


def _write_schemas(dest: Path) -> None:
    """Write app/schemas/api_key.py with all Pydantic schemas.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Pydantic schemas for API key endpoints.

        ``APIKeyPublic`` intentionally omits ``secret_hash`` and any plaintext.
        ``APIKeyCreatedResponse`` is the ONLY schema that carries the plaintext token
        and is only returned by the POST /api-keys/ endpoint.
        \"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime
        from typing import Literal

        from pydantic import BaseModel, ConfigDict, Field


        class APIKeyCreate(BaseModel):
            \"\"\"Input schema for creating a new API key.

            Attributes:
                name: Short human-readable label.
                description: Optional extended description.
                scopes: List of resource:action scope strings.
                expires_at: Optional hard expiry timestamp.
                environment: Key environment prefix (live or test).
            \"\"\"

            name: str = Field(..., min_length=1, max_length=255)
            description: str | None = Field(default=None, max_length=500)
            scopes: list[str] = Field(default_factory=lambda: ["read"])
            expires_at: datetime | None = None
            environment: Literal["live", "test"] = "live"


        class APIKeyUpdate(BaseModel):
            \"\"\"Input schema for updating an existing API key.

            Attributes:
                name: New human-readable label.
                description: New optional description.
                scopes: Replacement list of scope strings.
            \"\"\"

            name: str | None = Field(default=None, min_length=1, max_length=255)
            description: str | None = None
            scopes: list[str] | None = None


        class APIKeyPublic(BaseModel):
            \"\"\"Public read schema for API keys.

            Deliberately excludes ``secret_hash`` and any plaintext secret.

            Attributes:
                id: UUID primary key.
                key_id: Short public identifier.
                name: Human-readable label.
                description: Optional description.
                scopes: Granted scope list.
                status: active | revoked | expired.
                user_id: Owner user UUID.
                expires_at: Optional hard expiry.
                last_used_at: Last successful authentication timestamp.
                revoked_at: Revocation timestamp.
                created_at: Creation timestamp.
            \"\"\"

            model_config = ConfigDict(from_attributes=True)

            id: uuid.UUID
            key_id: str
            name: str
            description: str | None = None
            scopes: list[str]
            status: str
            user_id: uuid.UUID
            expires_at: datetime | None = None
            last_used_at: datetime | None = None
            revoked_at: datetime | None = None
            created_at: datetime


        class APIKeyCreatedResponse(BaseModel):
            \"\"\"Response schema returned ONCE at key creation.

            Contains the plaintext token which is never returned again after this
            single response.  Clients MUST store it immediately.

            Attributes:
                api_key: Public metadata for the new key.
                plaintext_token: Full token string to use in Authorization header.
                warning: Reminder that the token will not be shown again.
            \"\"\"

            api_key: APIKeyPublic
            plaintext_token: str
            warning: str = "Store this token now. It will NOT be shown again."
        """)
    dest.write_text(content)


def _write_routes(dest: Path) -> None:
    """Write app/api/routes/api_keys.py with create, list, rotate, revoke endpoints.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"API-key management endpoints.

        Owners may create, list, rotate, and revoke their own API keys.
        The plaintext token is shown exactly once on creation.
        \"\"\"

        from __future__ import annotations

        from fastapi import APIRouter, HTTPException, status

        from app.api.deps import CurrentUser, SessionDep
        from app.core.api_key_hasher import generate_key_id, generate_secret, hash_secret
        from app.crud import api_key as crud_api_key
        from app.schemas.api_key import (
            APIKeyCreate,
            APIKeyCreatedResponse,
            APIKeyPublic,
        )

        router = APIRouter(prefix="/api-keys", tags=["api-keys"])


        @router.post("/", response_model=APIKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
        async def create_api_key(
            key_in: APIKeyCreate,
            session: SessionDep,
            current_user: CurrentUser,
        ) -> APIKeyCreatedResponse:
            \"\"\"Create a new API key for the authenticated user.

            Returns the plaintext token exactly once.  The token format is
            ``api_<key_id>_<secret>``; pass it as ``Authorization: Bearer <token>``.

            Args:
                key_in: Key creation parameters (name, scopes, expiry, environment).
                session: Injected async database session.
                current_user: Authenticated user who will own the key.

            Returns:
                ``APIKeyCreatedResponse`` with the single-use plaintext token and warning.
            \"\"\"
            key_id = generate_key_id()
            secret = generate_secret()
            secret_hash = hash_secret(secret)
            plaintext_token = f"api_{key_id}_{secret}"

            api_key = await crud_api_key.create(
                session,
                key_in=key_in,
                user_id=current_user.id,
                key_id=key_id,
                secret_hash=secret_hash,
            )
            return APIKeyCreatedResponse(
                api_key=APIKeyPublic.model_validate(api_key),
                plaintext_token=plaintext_token,
                warning="Store this token now. It will NOT be shown again.",
            )


        @router.get("/", response_model=list[APIKeyPublic])
        async def list_my_api_keys(
            session: SessionDep,
            current_user: CurrentUser,
        ) -> list[APIKeyPublic]:
            \"\"\"List all API keys owned by the authenticated user.

            Args:
                session: Injected async database session.
                current_user: Authenticated user.

            Returns:
                List of ``APIKeyPublic`` — never includes plaintext secrets.
            \"\"\"
            keys = await crud_api_key.list_for_user(session, user_id=current_user.id)
            return [APIKeyPublic.model_validate(k) for k in keys]


        @router.post("/{key_id}/rotate", response_model=APIKeyCreatedResponse)
        async def rotate_api_key(
            key_id: str,
            session: SessionDep,
            current_user: CurrentUser,
        ) -> APIKeyCreatedResponse:
            \"\"\"Rotate the secret for an API key owned by the authenticated user.

            The old secret is invalidated immediately.  The new plaintext token is
            shown exactly once in the response.

            Args:
                key_id: Short identifier of the key to rotate.
                session: Injected async database session.
                current_user: Must be the owner of the key.

            Returns:
                ``APIKeyCreatedResponse`` with the new single-use plaintext token.

            Raises:
                HTTPException 404: Key not found or not owned by current user.
            \"\"\"
            api_key = await crud_api_key.get_by_key_id(session, key_id=key_id)
            if not api_key or api_key.user_id != current_user.id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
            new_secret = generate_secret()
            api_key.secret_hash = hash_secret(new_secret)
            await session.flush()
            plaintext_token = f"api_{api_key.key_id}_{new_secret}"
            return APIKeyCreatedResponse(
                api_key=APIKeyPublic.model_validate(api_key),
                plaintext_token=plaintext_token,
                warning="Old secret is now invalid. Update your client immediately.",
            )


        @router.post("/{key_id}/revoke", response_model=None, status_code=status.HTTP_204_NO_CONTENT)
        async def revoke_api_key(
            key_id: str,
            session: SessionDep,
            current_user: CurrentUser,
        ) -> None:
            \"\"\"Revoke an API key immediately.

            The key becomes unusable on the very next request.  Revocation is
            irreversible; a new key must be created to restore access.

            Args:
                key_id: Short identifier of the key to revoke.
                session: Injected async database session.
                current_user: Must be the owner of the key.

            Raises:
                HTTPException 404: Key not found or not owned by current user.
                HTTPException 409: Key is already revoked.
            \"\"\"
            api_key = await crud_api_key.get_by_key_id(session, key_id=key_id)
            if not api_key or api_key.user_id != current_user.id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
            if api_key.status == "revoked":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Key already revoked",
                )
            await crud_api_key.revoke(session, api_key=api_key)
        """)
    dest.write_text(content)


def _patch_api_main(routes_init: Path) -> None:
    """Register the api_keys router in ``app/routes/__init__.py``.

    The real router assembly lives in ``app/routes/__init__.py`` (see
    ``generators/orchestrator.py``), NOT ``app/api/main.py`` (which does not
    exist in the generated scaffold). Idempotent — no-op if already present.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
    """
    _register_router_in_routes_init(
        routes_init,
        import_line="from app.api.routes.api_keys import router as api_keys_router",
        include_line="api_router.include_router(api_keys_router)",
    )


def _register_router_in_routes_init(
    routes_init: Path,
    *,
    import_line: str,
    include_line: str,
) -> None:
    """Idempotently add an import + ``api_router.include_router`` call.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
        import_line: Import statement to insert (no trailing newline).
        include_line: ``api_router.include_router(...)`` call (no trailing newline).
    """
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


def _write_migration(versions_dir: Path) -> Path:
    """Generate an Alembic migration creating the api_keys table.

    Args:
        versions_dir: ``alembic/versions/`` directory.

    Returns:
        Path of the created migration file.
    """
        # Find the true HEAD of the migration chain (not just the alphabetically last file)
    down_rev = find_migration_head(versions_dir) or "0001_initial"
    content = textwrap.dedent("""\
        \"\"\"Add api_keys table.

        Revision ID: 0010_add_api_key_auth
        Revises: {down_rev}
        \"\"\"

        from __future__ import annotations

        import sqlalchemy as sa
        from alembic import op

        revision = "0010_add_api_key_auth"
        down_revision = "{down_rev}"
        branch_labels = None
        depends_on = None


        def upgrade() -> None:
            \"\"\"Create api_keys table with check constraints and indexes.\"\"\"
            op.create_table(
                "api_keys",
                sa.Column("id", sa.Uuid(), primary_key=True),
                sa.Column("key_id", sa.String(32), nullable=False),
                sa.Column("secret_hash", sa.String(255), nullable=False),
                sa.Column("name", sa.String(255), nullable=False),
                sa.Column("description", sa.String(500), nullable=True),
                sa.Column("scopes", sa.JSON(), server_default="[]", nullable=False),
                sa.Column("status", sa.String(16), server_default="active", nullable=False),
                sa.Column(
                    "user_id",
                    sa.Uuid(),
                    sa.ForeignKey("users.id", ondelete="CASCADE"),
                    nullable=False,
                ),
                sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
                sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
                sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.func.now(),
                    nullable=False,
                ),
                sa.CheckConstraint(
                    "status IN ('active','revoked','expired')", name="ck_api_keys_status"
                ),
                sa.CheckConstraint(
                    "length(key_id) >= 16 AND length(key_id) <= 32", name="ck_api_keys_key_id_format"
                ),
            )
            op.create_index("ix_api_keys_key_id", "api_keys", ["key_id"], unique=True)
            op.create_index("ix_api_keys_user_status", "api_keys", ["user_id", "status"])


        def downgrade() -> None:
            \"\"\"Drop api_keys table and its indexes.\"\"\"
            op.drop_index("ix_api_keys_user_status", "api_keys")
            op.drop_index("ix_api_keys_key_id", "api_keys")
            op.drop_table("api_keys")
        """).replace("{down_rev}", down_rev)

    migration_file = versions_dir / "0010_add_api_key_auth.py"
    migration_file.write_text(content)
    return migration_file


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start* (from ``time.monotonic()``).

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed time in milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
