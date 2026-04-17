"""TOOL-064: add_feature_toggles_api — upgrade a FastAPI project to a full API-driven
feature toggle system with DB persistence, percentage rollout, user allowlist, and
environment gating.

Builds on top of ``add_feature_flags`` (config/env-var flags).  If the old system is
present, env-var flags continue to take **priority** over DB flags.  New capabilities:

* ``FeatureToggle`` model (name, enabled, rollout_percentage, allowed_users JSON,
  environments JSON) persisted to ``feature_toggles`` table
* ``FeatureToggleService`` with ``is_enabled(flag, user_id, default)`` — checks DB,
  uses TTL cache
* ``RuleEvaluator`` — percentage rollout via ``hash(user_id + flag_name) % 100``,
  user allowlist, environment gate
* Admin REST API: CRUD at ``/feature-toggles`` + ``POST /{name}/evaluate``
* Alembic migration for the ``feature_toggles`` table
* Coexists with env-var flags: env vars win

Idempotency: if ``FeatureToggle`` model fingerprint is detected the tool returns
``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.auth_access.add_feature_toggles_api import add_feature_toggles_api

    result = add_feature_toggles_api(ToolInput(project_dir="/path/to/project"))
    print(result.status)         # "success"
    print(result.files_created)  # [.../feature_toggle.py, ...]
    print(result.next_steps)     # ["alembic upgrade head", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head


MCP_TOOL = {
    "name": "fastapi_add_feature_toggles_api",
    "description": (
        "Upgrade a FastAPI project to a full API-driven feature toggle system "
        "with DB persistence, percentage rollout, user allowlist, and environment gating."
    ),
    "tags": ["extend", "auth_access"],
    "entry": "add_feature_toggles_api",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_feature_toggles_api(inp: ToolInput) -> ToolResult:
    """Add a full API-driven feature toggle system to a FastAPI project.

    Reads the project at ``inp.project_dir``, writes all required files for
    toggle evaluation, service layer, REST API, and Alembic migration.
    Coexists with existing env-var feature flags (env vars take priority).

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
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    # --- Prerequisite check --------------------------------------------------
    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.REQUIREMENTS_TXT,
        Prereq.BASE_MODEL,
        Prereq.MODELS_INIT,
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

    # --- Pre-flight: idempotency check ---------------------------------------
    toggle_model_file = app_dir / "models" / "feature_toggle.py"
    if toggle_model_file.exists() and "FeatureToggle" in toggle_model_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["FeatureToggle model already present — toggle API system already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create: FeatureToggle model, service, evaluator, CRUD, routes, schemas, migration.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 1: FeatureToggle model -----------------------------------------
    _write_toggle_model(toggle_model_file)
    files_created.append(str(toggle_model_file))

    # Register FeatureToggle in app/models/__init__.py
    _patch_models_init(app_dir / "models" / "__init__.py", "feature_toggle", "FeatureToggle")
    files_modified.append(str(app_dir / "models" / "__init__.py"))

    # --- Step 2: Pydantic schemas --------------------------------------------
    schema_file = app_dir / "schemas" / "feature_toggle.py"
    _write_toggle_schemas(schema_file)
    files_created.append(str(schema_file))

    # --- Step 3: Async CRUD --------------------------------------------------
    crud_file = app_dir / "crud" / "feature_toggle.py"
    _write_toggle_crud(crud_file)
    files_created.append(str(crud_file))

    # --- Step 4: Rule evaluator ----------------------------------------------
    evaluator_file = app_dir / "features" / "evaluator.py"
    _write_toggle_evaluator(evaluator_file)
    files_created.append(str(evaluator_file))

    # --- Step 5: FeatureToggleService ----------------------------------------
    service_file = app_dir / "features" / "service.py"
    _write_toggle_service(service_file)
    files_created.append(str(service_file))

    # --- Step 6: features __init__ re-exports --------------------------------
    features_init = app_dir / "features" / "__init__.py"
    _write_features_init(features_init)
    files_created.append(str(features_init))

    # --- Step 7: REST routes -------------------------------------------------
    routes_file = app_dir / "api" / "routes" / "feature_toggles.py"
    _write_toggle_routes(routes_file)
    files_created.append(str(routes_file))

    # --- Step 8: Patch app/core/config.py ------------------------------------
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- Step 9: Patch app/routes/__init__.py --------------------------------
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # --- Step 10: Alembic migration ------------------------------------------
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        migration_file = _write_toggle_migration(versions_dir)
        files_created.append(str(migration_file))

    # --- Validate all generated .py files parse cleanly ---------------------
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
            "Feature toggle API system added: model, schemas, CRUD, evaluator, service, routes.",
            "Percentage rollout uses hash(user_id + flag_name) % 100 — fully deterministic.",
            "User allowlist takes priority over percentage rollout.",
            "Environment gate blocks evaluation when app env is not in allowed list.",
            "Env-var flags (add_feature_flags) take priority over DB toggles.",
            "In-memory TTL cache avoids DB hit on hot paths (FEATURE_TOGGLES_CACHE_TTL_SECONDS).",
        ],
        next_steps=[
            "alembic upgrade head",
            "Set FEATURE_TOGGLES_CACHE_TTL_SECONDS=60 in .env (default: 60)",
            "Wire router: include_router(feature_toggles.router) in app/routes/__init__.py",
            "Admin endpoints require superuser — use CurrentSuperuser dep.",
            "POST /feature-toggles/{name}/evaluate for client-side flag checks.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Step helpers — each ≤ 50 LOC
# ---------------------------------------------------------------------------

def _patch_models_init(models_init: Path, module: str, cls: str) -> None:
    """Append a model import to ``app/models/__init__.py`` idempotently.

    Args:
        models_init: Path to models __init__.py.
        module: Module name under app.models (e.g. 'feature_toggle').
        cls: Class name to import (e.g. 'FeatureToggle').
    """
    if not models_init.exists():
        return
    content = models_init.read_text()
    marker = f"from app.models.{module} import {cls}"
    if marker in content:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += f"{marker}  # noqa: F401\n"
    models_init.write_text(content)


def _patch_config(config_file: Path) -> None:
    """Add FEATURE_TOGGLES_CACHE_TTL_SECONDS to Settings idempotently.

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    content = config_file.read_text()
    if "FEATURE_TOGGLES_CACHE_TTL_SECONDS" in content:
        return
    marker = "class Settings"
    if marker not in content:
        return
    insert = "\n    FEATURE_TOGGLES_CACHE_TTL_SECONDS: int = 60\n"
    # Insert after the class definition line
    idx = content.find(marker)
    line_end = content.find("\n", idx)
    content = content[: line_end + 1] + insert + content[line_end + 1 :]
    config_file.write_text(content)


def _patch_routes_init(routes_init: Path) -> None:
    """Register feature_toggles router in ``app/routes/__init__.py`` idempotently.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
    """
    content = routes_init.read_text()
    if "feature_toggles" in content:
        return
    addition = textwrap.dedent("""\

        # Feature Toggles API
        from app.api.routes import feature_toggles  # noqa: F401
        api_router.include_router(feature_toggles.router)
    """)
    content = content.rstrip() + addition
    routes_init.write_text(content)


def _write_toggle_model(dest: Path) -> None:
    """Write ``app/models/feature_toggle.py`` with FeatureToggle ORM model.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"ORM model for the API-driven feature toggle system.\"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime

        from sqlalchemy import Boolean, DateTime, Integer, JSON, String, Uuid, func
        from sqlalchemy.orm import Mapped, mapped_column

        from app.models.base import Base


        class FeatureToggle(Base):
            \"\"\"Persistent feature toggle with per-user and per-environment rules.

            Attributes:
                id: UUID primary key.
                name: Unique, URL-safe toggle name.
                enabled: Master on/off switch.
                rollout_percentage: 0-100; deterministic hash-based rollout.
                allowed_users: JSON list of user-id strings always granted access.
                environments: JSON list of allowed environment strings.
                created_at: UTC creation timestamp.
                updated_at: UTC last-updated timestamp.
            \"\"\"

            __tablename__ = "feature_toggles"

            id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
            name: Mapped[str] = mapped_column(
                String(127), unique=True, nullable=False, index=True
            )
            enabled: Mapped[bool] = mapped_column(
                Boolean, nullable=False, server_default="false"
            )
            rollout_percentage: Mapped[int] = mapped_column(
                Integer, nullable=False, server_default="100"
            )
            allowed_users: Mapped[list] = mapped_column(
                JSON, nullable=False, server_default="[]"
            )
            environments: Mapped[list] = mapped_column(
                JSON, nullable=False, server_default="[]"
            )
            created_at: Mapped[datetime] = mapped_column(
                DateTime(timezone=True), server_default=func.now(), nullable=False
            )
            updated_at: Mapped[datetime] = mapped_column(
                DateTime(timezone=True),
                server_default=func.now(),
                onupdate=func.now(),
                nullable=False,
            )
        """)
    dest.write_text(content)


def _write_toggle_schemas(dest: Path) -> None:
    """Write ``app/schemas/feature_toggle.py`` with Pydantic schemas.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Pydantic schemas for the feature toggle API.\"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime

        from pydantic import BaseModel, ConfigDict, Field


        class ToggleCreate(BaseModel):
            \"\"\"Input schema for creating a feature toggle.

            Attributes:
                name: Unique toggle name (URL-safe).
                enabled: Whether the toggle is active.
                rollout_percentage: Percentage of users to receive the feature.
                allowed_users: User IDs always granted access.
                environments: Environments where toggle is active (empty = all).
            \"\"\"

            name: str = Field(..., min_length=1, max_length=127)
            enabled: bool = Field(default=False)
            rollout_percentage: int = Field(default=100, ge=0, le=100)
            allowed_users: list[str] = Field(default_factory=list)
            environments: list[str] = Field(default_factory=list)


        class ToggleUpdate(BaseModel):
            \"\"\"Input schema for partially updating a feature toggle.\"\"\"

            model_config = ConfigDict(from_attributes=True)

            enabled: bool | None = None
            rollout_percentage: int | None = Field(default=None, ge=0, le=100)
            allowed_users: list[str] | None = None
            environments: list[str] | None = None


        class ToggleRead(BaseModel):
            \"\"\"Output schema for feature toggle API responses.\"\"\"

            model_config = ConfigDict(from_attributes=True)

            id: uuid.UUID
            name: str
            enabled: bool
            rollout_percentage: int
            allowed_users: list[str]
            environments: list[str]
            created_at: datetime
            updated_at: datetime


        class ToggleEvaluate(BaseModel):
            \"\"\"Request schema for the evaluate endpoint.

            Attributes:
                user_id: The user to evaluate the toggle for.
                environment: Current runtime environment.
            \"\"\"

            user_id: str | None = None
            environment: str = "production"


        class ToggleEvaluateResult(BaseModel):
            \"\"\"Response schema for the evaluate endpoint.\"\"\"

            name: str
            enabled: bool
            reason: str
        """)
    dest.write_text(content)


def _write_toggle_crud(dest: Path) -> None:
    """Write ``app/crud/feature_toggle.py`` with async CRUD helpers.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Async CRUD helpers for FeatureToggle.\"\"\"

        from __future__ import annotations

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.models.feature_toggle import FeatureToggle
        from app.schemas.feature_toggle import ToggleCreate, ToggleUpdate


        async def get_by_name(session: AsyncSession, *, name: str) -> FeatureToggle | None:
            \"\"\"Fetch a FeatureToggle by its unique name.

            Args:
                session: Async SQLAlchemy session.
                name: Toggle name string.

            Returns:
                FeatureToggle ORM instance, or None if not found.
            \"\"\"
            stmt = select(FeatureToggle).where(FeatureToggle.name == name)
            return (await session.execute(stmt)).scalar_one_or_none()


        async def list_toggles(session: AsyncSession) -> list[FeatureToggle]:
            \"\"\"Return all FeatureToggle rows ordered by name.

            Args:
                session: Async SQLAlchemy session.

            Returns:
                List of FeatureToggle ORM instances.
            \"\"\"
            stmt = select(FeatureToggle).order_by(FeatureToggle.name)
            return list((await session.execute(stmt)).scalars().all())


        async def create(
            session: AsyncSession,
            *,
            toggle_in: ToggleCreate,
        ) -> FeatureToggle:
            \"\"\"Create a new FeatureToggle and flush to DB.

            Args:
                session: Async SQLAlchemy session.
                toggle_in: Validated create schema.

            Returns:
                Newly created FeatureToggle ORM instance.
            \"\"\"
            toggle = FeatureToggle(**toggle_in.model_dump())
            session.add(toggle)
            await session.flush()
            await session.refresh(toggle)
            return toggle


        async def update(
            session: AsyncSession,
            *,
            toggle: FeatureToggle,
            toggle_in: ToggleUpdate,
        ) -> FeatureToggle:
            \"\"\"Apply a partial update to a FeatureToggle.

            Args:
                session: Async SQLAlchemy session.
                toggle: Existing FeatureToggle ORM instance.
                toggle_in: Validated partial update schema.

            Returns:
                Updated FeatureToggle ORM instance.
            \"\"\"
            for field, value in toggle_in.model_dump(exclude_unset=True).items():
                setattr(toggle, field, value)
            await session.flush()
            await session.refresh(toggle)
            return toggle


        async def delete(session: AsyncSession, *, toggle: FeatureToggle) -> None:
            \"\"\"Delete a FeatureToggle from the database.

            Args:
                session: Async SQLAlchemy session.
                toggle: FeatureToggle ORM instance to delete.
            \"\"\"
            await session.delete(toggle)
            await session.flush()
        """)
    dest.write_text(content)


def _write_toggle_evaluator(dest: Path) -> None:
    """Write ``app/features/evaluator.py`` with rule evaluation logic.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Rule evaluator for feature toggles.

        Evaluation order (first match wins):
        1. Toggle disabled → False
        2. User in allowed_users allowlist → True
        3. environments list non-empty and current env not in list → False
        4. Percentage rollout via deterministic hash → True/False
        \"\"\"

        from __future__ import annotations

        import hashlib


        def evaluate(
            toggle: object,
            *,
            user_id: str | None = None,
            environment: str = "production",
        ) -> tuple[bool, str]:
            \"\"\"Evaluate whether a toggle is active for a given context.

            Uses percentage rollout via ``hash(user_id + toggle.name) % 100``
            which is fully deterministic — the same user always gets the same
            bucket for a given toggle name.

            Args:
                toggle: FeatureToggle ORM instance (duck-typed for testability).
                user_id: Optional user identifier string for bucketing.
                environment: Current runtime environment string.

            Returns:
                Tuple of (enabled: bool, reason: str).
            \"\"\"
            if not toggle.enabled:
                return False, "disabled"

            if user_id and user_id in (toggle.allowed_users or []):
                return True, "allowlist"

            envs = toggle.environments or []
            if envs and environment not in envs:
                return False, "environment_gate"

            pct = toggle.rollout_percentage
            if pct >= 100:
                return True, "full_rollout"
            if pct <= 0:
                return False, "zero_rollout"

            if user_id:
                bucket = _bucket(toggle.name, user_id)
                if bucket < pct:
                    return True, f"rollout:{pct}%"
                return False, f"rollout:{pct}%"

            return False, "no_user_id"


        def _bucket(toggle_name: str, user_id: str) -> int:
            \"\"\"Return a deterministic 0-99 bucket for (toggle_name, user_id).

            Args:
                toggle_name: Toggle name string.
                user_id: User identifier string.

            Returns:
                Integer in range [0, 99].
            \"\"\"
            payload = f"{user_id}{toggle_name}".encode("utf-8")
            digest = hashlib.sha256(payload).digest()
            return int.from_bytes(digest[:4], "big", signed=False) % 100
        """)
    dest.write_text(content)


def _write_toggle_service(dest: Path) -> None:
    """Write ``app/features/service.py`` with FeatureToggleService.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"FeatureToggleService — high-level API with TTL caching.

        Env-var flags (from add_feature_flags) take **priority** over DB toggles:
        if ``os.getenv(flag_name.upper())`` is set to a truthy or falsy string,
        the DB is not consulted and that value is returned immediately.
        \"\"\"

        from __future__ import annotations

        import os
        import time
        from typing import Any

        from sqlalchemy.ext.asyncio import AsyncSession

        from app.crud.feature_toggle import (
            create,
            delete,
            get_by_name,
            list_toggles,
            update,
        )
        from app.features.evaluator import evaluate
        from app.schemas.feature_toggle import ToggleCreate, ToggleRead, ToggleUpdate

        _CACHE: dict[str, tuple[float, Any]] = {}
        _CACHE_TTL: int = int(os.getenv("FEATURE_TOGGLES_CACHE_TTL_SECONDS", "60"))

        _TRUTHY = {"1", "true", "yes", "on"}
        _FALSY = {"0", "false", "no", "off"}


        class FeatureToggleService:
            \"\"\"Service layer for feature toggle evaluation and administration.

            Provides ``is_enabled`` for hot-path callers and CRUD wrappers for
            the admin API.  All results are cached in-process for
            ``FEATURE_TOGGLES_CACHE_TTL_SECONDS`` seconds.

            Attributes:
                _session: Async SQLAlchemy session injected at construction time.
            \"\"\"

            def __init__(self, session: AsyncSession) -> None:
                self._session = session

            async def is_enabled(
                self,
                name: str,
                *,
                user_id: str | None = None,
                environment: str = "production",
                default: bool = False,
            ) -> bool:
                \"\"\"Return whether a toggle is active for the given context.

                Checks env-var override first, then in-memory cache, then DB.

                Args:
                    name: Toggle name string.
                    user_id: Optional user ID for per-user rules.
                    environment: Current runtime environment.
                    default: Fallback when toggle is missing or evaluation fails.

                Returns:
                    True if the toggle is active for this context, else False.
                \"\"\"
                env_val = os.getenv(name.upper(), "").strip().lower()
                if env_val in _TRUTHY:
                    return True
                if env_val in _FALSY:
                    return False

                toggle = await self._load(name)
                if toggle is None:
                    return default
                enabled, _ = evaluate(toggle, user_id=user_id, environment=environment)
                return enabled

            async def create_toggle(self, toggle_in: ToggleCreate) -> ToggleRead:
                \"\"\"Create a new feature toggle and invalidate cache.

                Args:
                    toggle_in: Validated create schema.

                Returns:
                    ToggleRead schema of the newly created toggle.
                \"\"\"
                toggle = await create(self._session, toggle_in=toggle_in)
                _invalidate(toggle.name)
                return ToggleRead.model_validate(toggle)

            async def update_toggle(self, name: str, toggle_in: ToggleUpdate) -> ToggleRead | None:
                \"\"\"Update a toggle and invalidate cache.

                Args:
                    name: Toggle name to update.
                    toggle_in: Validated partial update schema.

                Returns:
                    Updated ToggleRead, or None if toggle not found.
                \"\"\"
                toggle = await get_by_name(self._session, name=name)
                if toggle is None:
                    return None
                toggle = await update(self._session, toggle=toggle, toggle_in=toggle_in)
                _invalidate(toggle.name)
                return ToggleRead.model_validate(toggle)

            async def list_toggles(self) -> list[ToggleRead]:
                \"\"\"Return all toggles as ToggleRead schemas.

                Returns:
                    List of ToggleRead schemas ordered by name.
                \"\"\"
                rows = await list_toggles(self._session)
                return [ToggleRead.model_validate(r) for r in rows]

            async def _load(self, name: str) -> object | None:
                \"\"\"Load toggle from cache or DB.

                Args:
                    name: Toggle name string.

                Returns:
                    FeatureToggle ORM instance or None.
                \"\"\"
                entry = _CACHE.get(name)
                if entry is not None:
                    cached_at, value = entry
                    if time.monotonic() - cached_at < _CACHE_TTL:
                        return value
                toggle = await get_by_name(self._session, name=name)
                _CACHE[name] = (time.monotonic(), toggle)
                return toggle


        def _invalidate(name: str) -> None:
            \"\"\"Evict a toggle from the in-process cache.

            Args:
                name: Toggle name to evict.
            \"\"\"
            _CACHE.pop(name, None)
        """)
    dest.write_text(content)


def _write_features_init(dest: Path) -> None:
    """Write ``app/features/__init__.py`` with public re-exports.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Feature toggle subsystem — public re-exports.\"\"\"

        from app.features.evaluator import evaluate  # noqa: F401
        from app.features.service import FeatureToggleService  # noqa: F401

        __all__ = ["FeatureToggleService", "evaluate"]
        """)
    dest.write_text(content)


def _write_toggle_routes(dest: Path) -> None:
    """Write ``app/api/routes/feature_toggles.py`` with admin REST endpoints.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Admin REST API for feature toggle management.

        Endpoints:
          GET    /feature-toggles               — list all toggles
          POST   /feature-toggles               — create toggle (superuser)
          PUT    /feature-toggles/{name}        — update toggle (superuser)
          DELETE /feature-toggles/{name}        — delete toggle (superuser)
          POST   /feature-toggles/{name}/evaluate — evaluate for a user context
        \"\"\"

        from __future__ import annotations

        from fastapi import APIRouter, HTTPException, status

        from app.api.deps import CurrentSuperuser, SessionDep
        from app.features.service import FeatureToggleService
        from app.schemas.feature_toggle import (
            ToggleCreate,
            ToggleEvaluate,
            ToggleEvaluateResult,
            ToggleRead,
            ToggleUpdate,
        )

        router = APIRouter(prefix="/feature-toggles", tags=["feature-toggles"])


        @router.get("/", response_model=list[ToggleRead])
        async def list_toggles(
            session: SessionDep,
            current_user: CurrentSuperuser,
        ) -> list[ToggleRead]:
            \"\"\"List all feature toggles. Superuser only.

            Args:
                session: Injected async DB session.
                current_user: Must be a superuser.

            Returns:
                List of all ToggleRead schemas.
            \"\"\"
            svc = FeatureToggleService(session)
            return await svc.list_toggles()


        @router.post("/", response_model=ToggleRead, status_code=status.HTTP_201_CREATED)
        async def create_toggle(
            toggle_in: ToggleCreate,
            session: SessionDep,
            current_user: CurrentSuperuser,
        ) -> ToggleRead:
            \"\"\"Create a new feature toggle. Superuser only.

            Args:
                toggle_in: Validated toggle create payload.
                session: Injected async DB session.
                current_user: Must be a superuser.

            Raises:
                HTTPException: 409 if toggle name already exists.
            \"\"\"
            from app.crud.feature_toggle import get_by_name
            existing = await get_by_name(session, name=toggle_in.name)
            if existing:
                raise HTTPException(status_code=409, detail="Toggle name already exists")
            svc = FeatureToggleService(session)
            return await svc.create_toggle(toggle_in)


        @router.put("/{name}", response_model=ToggleRead)
        async def update_toggle(
            name: str,
            toggle_in: ToggleUpdate,
            session: SessionDep,
            current_user: CurrentSuperuser,
        ) -> ToggleRead:
            \"\"\"Update a feature toggle. Superuser only.

            Args:
                name: Toggle name path parameter.
                toggle_in: Validated partial update payload.
                session: Injected async DB session.
                current_user: Must be a superuser.

            Raises:
                HTTPException: 404 if toggle not found.
            \"\"\"
            svc = FeatureToggleService(session)
            result = await svc.update_toggle(name, toggle_in)
            if result is None:
                raise HTTPException(status_code=404, detail="Toggle not found")
            return result


        @router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
        async def delete_toggle(
            name: str,
            session: SessionDep,
            current_user: CurrentSuperuser,
        ) -> None:
            \"\"\"Delete a feature toggle. Superuser only.

            Args:
                name: Toggle name path parameter.
                session: Injected async DB session.
                current_user: Must be a superuser.

            Raises:
                HTTPException: 404 if toggle not found.
            \"\"\"
            from app.crud.feature_toggle import delete, get_by_name
            toggle = await get_by_name(session, name=name)
            if not toggle:
                raise HTTPException(status_code=404, detail="Toggle not found")
            await delete(session, toggle=toggle)


        @router.post("/{name}/evaluate", response_model=ToggleEvaluateResult)
        async def evaluate_toggle(
            name: str,
            body: ToggleEvaluate,
            session: SessionDep,
            current_user: CurrentSuperuser,
        ) -> ToggleEvaluateResult:
            \"\"\"Evaluate a toggle for a given user/environment context.

            Args:
                name: Toggle name path parameter.
                body: Evaluation context (user_id, environment).
                session: Injected async DB session.
                current_user: Must be a superuser.

            Raises:
                HTTPException: 404 if toggle not found.
            \"\"\"
            from app.crud.feature_toggle import get_by_name
            from app.features.evaluator import evaluate
            toggle = await get_by_name(session, name=name)
            if not toggle:
                raise HTTPException(status_code=404, detail="Toggle not found")
            enabled, reason = evaluate(
                toggle, user_id=body.user_id, environment=body.environment
            )
            return ToggleEvaluateResult(name=name, enabled=enabled, reason=reason)
        """)
    dest.write_text(content)


def _write_toggle_migration(versions_dir: Path) -> Path:
    """Generate an Alembic migration creating the feature_toggles table.

    Args:
        versions_dir: ``alembic/versions/`` directory.

    Returns:
        Path of the created migration file.
    """
    rev_id = "0064_add_feature_toggles_api"
    down_rev = find_migration_head(versions_dir) or "0001_initial"
    content = textwrap.dedent("""\
        \"\"\"Add feature_toggles table for API-driven toggle system.

        Revision ID: {rev_id}
        Revises: {down_rev}
        Create Date: auto-generated by add_feature_toggles_api tool
        \"\"\"

        from __future__ import annotations

        import sqlalchemy as sa
        from alembic import op

        revision = "{rev_id}"
        down_revision = "{down_rev}"
        branch_labels = None
        depends_on = None


        def upgrade() -> None:
            \"\"\"Create feature_toggles table with index on name.\"\"\"
            op.create_table(
                "feature_toggles",
                sa.Column("id", sa.Uuid(), primary_key=True),
                sa.Column("name", sa.String(127), unique=True, nullable=False),
                sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
                sa.Column("rollout_percentage", sa.Integer(), server_default="100", nullable=False),
                sa.Column("allowed_users", sa.JSON(), server_default="[]", nullable=False),
                sa.Column("environments", sa.JSON(), server_default="[]", nullable=False),
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.func.now(),
                    nullable=False,
                ),
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.func.now(),
                    nullable=False,
                ),
                sa.CheckConstraint(
                    "rollout_percentage BETWEEN 0 AND 100",
                    name="ck_feature_toggles_rollout_range",
                ),
            )
            op.create_index("ix_feature_toggles_name", "feature_toggles", ["name"], unique=True)


        def downgrade() -> None:
            \"\"\"Drop feature_toggles table and its index.\"\"\"
            op.drop_index("ix_feature_toggles_name", "feature_toggles")
            op.drop_table("feature_toggles")
        """).format(rev_id=rev_id, down_rev=down_rev)

    migration_file = versions_dir / f"{rev_id}.py"
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
